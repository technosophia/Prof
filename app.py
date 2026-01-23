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
from shared.translate import init_translations_multiple, _
from shared.config import init_config, get_config

# Initialize configuration (one line) - BEFORE ANY OTHER IMPORTS THAT USE CONFIG
config = init_config("config.json")

from shared.logging import log, configure_logging_from_dict
# IMPORTANT: Don't alias 'llm' to avoid name conflicts
from shared.llm import llm_generate, set_current_llm, get_available_llms, get_current_llm_info

# Import user management
from shared.users import user_manager, init_user_manager
from shared.database import init_database, db_manager
# Import conversation management
from shared.conversation import conversation_manager, init_conversation_manager, Message

# Import UI registry system
from shared.ui_registry import UIRegistry, register_ui_module
# Import module handler
from shared.module_handler import ModuleHandler, get_active_modules, toggle_module

# Configure logging from config (one line)
configure_logging_from_dict(config.get("logging", {}))

# Initialize database
db_path = os.path.join("data", "app.db") if os.path.exists("data") else None
init_database(use_memory=False, db_path=db_path)

# Initialize user manager with default users
init_user_manager(create_default_users=True)

# Initialize conversation manager
init_conversation_manager()

# Initialize translator with Streamlit session support
translator = init_translations_multiple("en", ["shared", "translations"])

# Initialize Module Handler - store in session state
if 'module_handler' not in st.session_state:
    log("info", "Initializing module handler in session state")
    st.session_state.module_handler = ModuleHandler()
    st.session_state.module_handler.initialize()

# Use the session state module handler
module_handler = st.session_state.module_handler

# Load active module UIs immediately
active_modules = module_handler.get_active_modules()
log("info", f"Active modules: {active_modules}")
for module_name in active_modules:
    ui_module = module_handler.load_module_ui(module_name)
    if ui_module:
        log("info", f"Successfully loaded UI for module: {module_name}")
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


def get_conversation_history_for_llm(messages):
    """Convert conversation messages to LLM history format."""
    history = []
    for msg in messages:
        if msg.role in ["user", "assistant", "system"]:
            history.append({
                "role": msg.role,
                "content": msg.content
            })
    return history

async def generate_llm_response(user_message, conversation_history, current_llm_info):
    """Generate LLM response with conversation history."""
    # Prepare conversation history for LLM
    llm_history = get_conversation_history_for_llm(conversation_history)

    # Clear previous streaming buffer
    st.session_state.stream_buffer = ""
    st.session_state.streaming_active = True

    # Create a placeholder for the streaming response
    response_placeholder = st.empty()

    # Define streaming callback
    def stream_callback(chunk):
        st.session_state.stream_buffer += chunk
        response_placeholder.markdown(st.session_state.stream_buffer)

    try:
        # Use llm_generate with conversation history
        response = await llm_generate(
            user_message.strip(),
            stream_callback,
            conversation_history=llm_history
        )

        st.session_state.streaming_active = False
        return response
    except Exception as e:
        error_msg = f"Error calling LLM: {str(e)}"
        log("error", error_msg, exc_info=True)
        st.session_state.streaming_active = False
        raise Exception(error_msg)

def main():
    # Log main function entry
    log("debug", "Entering main function")

    # Get config inside main function
    current_config = get_config()

    # Initialize session state for page navigation
    if "current_page" not in st.session_state:
        st.session_state.current_page = "chat"

    # Initialize session state for conversation management
    if "current_conversation_id" not in st.session_state:
        st.session_state.current_conversation_id = None
    if "conversation_messages" not in st.session_state:
        st.session_state.conversation_messages = []
    if "new_conversation_title" not in st.session_state:
        st.session_state.new_conversation_title = "New Conversation"
    if "show_new_conversation_form" not in st.session_state:
        st.session_state.show_new_conversation_form = False
    if "editing_conversation_id" not in st.session_state:
        st.session_state.editing_conversation_id = None

    # Initialize session state for LLM response
    if "streaming_active" not in st.session_state:
        st.session_state.streaming_active = False
    if "stream_buffer" not in st.session_state:
        st.session_state.stream_buffer = ""

    # Initialize session state for regeneration
    if "regenerating_message_id" not in st.session_state:
        st.session_state.regenerating_message_id = None

    # Initialize session state for user management
    if "current_user" not in st.session_state:
        st.session_state.current_user = None
    if "show_user_form" not in st.session_state:
        st.session_state.show_user_form = False
    if "edit_user_id" not in st.session_state:
        st.session_state.edit_user_id = None

    # Initialize session state for UI modules
    if "ui_modules_initialized" not in st.session_state:
        st.session_state.ui_modules_initialized = False

    # Sidebar for language, LLM, navigation, and injected UI modules
    with st.sidebar:
        st.title("🌍 " + _("language_select"))

        # Show available languages
        available_langs = list(translator.translations.keys())

        # Log available languages
        log("debug", f"Available languages: {available_langs}")

        # Language selector
        lang_option = st.selectbox(
            _("language_select"),
            options=available_langs,
            format_func=lambda x: "English" if x == "en" else "Français",
            index=0 if st.session_state.current_language == "en" else 1,
            key="language_selector"
        )

        # Check if language changed
        if lang_option != st.session_state.current_language:
            old_lang = st.session_state.current_language
            st.session_state.current_language = lang_option
            translator.set_language(lang_option)
            log("info", f"Language changed from '{old_lang}' to '{lang_option}'")
            st.rerun()

        # Navigation
        st.title("🧭 Navigation")

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

        # LLM Selection
        st.title("🤖 " + _("llm_selection"))

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
                _("select_llm"),
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

        # INJECTION POINT 1: Sidebar Content from UI Modules
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
    st.title(_("hello_world"))

    # INJECTION POINT 2: Main Header Content from UI Modules
    header_contents = ui_registry.render_all("main_header")

    # INJECTION POINT 3: Main Content from UI Modules (before conversation interface)
    main_contents_before = ui_registry.render_all("main_before_conversation")

    # INJECTION POINT 4: Main Content when no user is logged in
    no_user_contents = ui_registry.render_all("main_no_user")

    # If no UI modules rendered anything for the current page/state, show default content
    if not any([header_contents, main_contents_before, no_user_contents]):
        if st.session_state.current_page == "admin":
            # This will be handled by admin_ui.py via UI registry
            st.info("Admin interface not loaded. Please check if admin_ui.py is in the shared directory.")
        else:
            # Chat page default content
            if st.session_state.current_user:
                if st.session_state.current_conversation_id:
                    # This will be handled by conversation_ui.py via UI registry
                    st.info("Conversation interface not loaded. Please check if conversation_ui.py is in the shared directory.")
                else:
                    st.divider()
                    st.info("💬 Select a conversation from the sidebar or create a new one to start chatting.")
            else:
                st.info("👤 Please log in to start chatting.")

    # INJECTION POINT 5: Main Content after conversation interface
    main_contents_after = ui_registry.render_all("main_after_conversation")
    for content in main_contents_after:
        if content:
            st.divider()

    # INJECTION POINT 6: Main Footer Content
    main_footer = ui_registry.render_all("main_footer")
    for content in main_footer:
        if content:
            st.divider()

if __name__ == "__main__":
    main()
