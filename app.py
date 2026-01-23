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
from shared.translate import init_translations_streamlit, _streamlit as _
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
translator = init_translations_streamlit("en", "translations")

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

def show_admin_page():
    """Display the Admin page."""
    st.title("🔧 Admin Panel")

    # Get active modules - USE THE SINGLETON INSTANCE
    active_modules = module_handler.get_active_modules()
    all_modules = module_handler.get_all_modules()

    # Module Management Section
    st.header("📦 Module Management")

    col1, col2 = st.columns([3, 1])
    with col1:
        st.subheader("Available Modules")
    with col2:
        if st.button("🔄 Refresh Modules"):
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
            if is_active:
                if st.button("Disable", key=f"disable_{module_name}"):
                    log("debug", f"Attempting to disable module: {module_name}")
                    log("debug", f"Current active modules: {module_handler.active_modules}")
                    log("debug", f"Module in modules dict: {module_name in module_handler.modules}")

                    if module_handler.toggle_module(module_name, False):
                        # Force UI registry to refresh
                        st.session_state.ui_registry = UIRegistry()
                        # Pass the CURRENT module handler instance
                        st.session_state.ui_registry.set_module_handler(module_handler)
                        st.session_state.ui_registry.initialize()
                        st.session_state.ui_modules_initialized = False
                        # Also save modules file
                        module_handler._save_modules_file()
                        st.success(f"Module '{module_name}' disabled")
                        st.rerun()
                    else:
                        log("error", f"Toggle failed for {module_name}")
            else:
                if st.button("Enable", key=f"enable_{module_name}"):
                    log("debug", f"Attempting to enable module: {module_name}")
                    if module_handler.toggle_module(module_name, True):
                        log("debug", f"Toggle succeeded for {module_name}")
                        # Force UI registry to refresh
                        st.session_state.ui_registry = UIRegistry()
                        st.session_state.ui_registry.initialize()
                        st.session_state.ui_modules_initialized = False
                        # Also save modules file
                        module_handler._save_modules_file()
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
        st.write(f"**UI Registry Modules:** {len(ui_registry.modules)}")

    with col2:
        st.subheader("Database")
        st.write(f"**Path:** {db_path}")
        st.write(f"**User Count:** {user_manager.get_user_count()}")

        # Count conversations - FIXED VERSION
        from shared.conversation import ConversationTable  # Import the table class
        with db_manager.get_session() as session:
            from sqlalchemy import func
            conv_count = session.query(func.count(ConversationTable.id)).scalar()
            st.write(f"**Conversation Count:** {conv_count}")

    # LLM Status Section
    st.header("🤖 LLM Status")
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
    if st.session_state.current_page == "admin":
        show_admin_page()
    else:
        # Chat page (default)
        st.title(_("hello_world"))

        # INJECTION POINT 2: Main Header Content from UI Modules
        header_contents = ui_registry.render_all("main_header")

        # INJECTION POINT 3: Main Content from UI Modules (before conversation interface)
        main_contents_before = ui_registry.render_all("main_before_conversation")

        # Conversation Interface (only show if user is logged in)
        if st.session_state.current_user:
            # Show current conversation or prompt to create one
            if not st.session_state.current_conversation_id:
                st.divider()
                st.info("💬 Select a conversation from the sidebar or create a new one to start chatting.")
            else:
                # Get current conversation info
                current_conv = conversation_manager.get_conversation(
                    st.session_state.current_conversation_id,
                    include_messages=False
                )

                if current_conv:
                    # Conversation header
                    col1, col2, col3, col4 = st.columns([4, 1, 1, 1])
                    with col1:
                        st.subheader(f"💬 {current_conv.title}")
                    with col2:
                        # Refresh button
                        if st.button("🔄 Refresh", help="Reload conversation from database"):
                            conversation = conversation_manager.get_conversation(
                                st.session_state.current_conversation_id,
                                include_messages=True
                            )
                            if conversation:
                                st.session_state.conversation_messages = conversation.messages
                            st.rerun()
                    with col3:
                        # Clear button
                        if st.button("🗑️ Clear", help="Clear all messages in this conversation"):
                            if conversation_manager.clear_conversation_messages(st.session_state.current_conversation_id):
                                st.session_state.conversation_messages = []
                                st.success("Conversation cleared")
                                st.rerun()
                    with col4:
                        # Regenerate button - only enable if there are messages and the last message is from assistant
                        has_messages = len(st.session_state.conversation_messages) > 0
                        last_is_assistant = has_messages and st.session_state.conversation_messages[-1].role == "assistant"

                        if st.button("🔄 Regenerate",
                                   help="Regenerate the last assistant response",
                                   disabled=not (has_messages and last_is_assistant),
                                   type="secondary"):
                            # Set regeneration flag and trigger regeneration
                            st.session_state.regenerating_message_id = len(st.session_state.conversation_messages) - 1
                            st.rerun()

                    # Display conversation messages
                    st.divider()

                    if st.session_state.conversation_messages:
                        for i, message in enumerate(st.session_state.conversation_messages):
                            if message.role == "user":
                                with st.chat_message("user"):
                                    st.write(message.content)
                            elif message.role == "assistant":
                                with st.chat_message("assistant"):
                                    st.write(message.content)

                                    # Add regenerate button for each assistant message
                                    if i == len(st.session_state.conversation_messages) - 1:  # Only for last message
                                        col_a, col_b = st.columns([1, 6])
                                        with col_a:
                                            if st.button("🔄",
                                                       key=f"regenerate_{i}",
                                                       help="Regenerate this response"):
                                                st.session_state.regenerating_message_id = i
                                                st.rerun()
                            elif message.role == "system":
                                with st.container():
                                    st.markdown(f"*System: {message.content}*")

                    # Handle regeneration if triggered
                    if (st.session_state.regenerating_message_id is not None and
                        st.session_state.regenerating_message_id < len(st.session_state.conversation_messages)):

                        # Get the message index to regenerate
                        regen_index = st.session_state.regenerating_message_id

                        # Find the last user message before this assistant message
                        user_message = ""
                        for i in range(regen_index, -1, -1):
                            if st.session_state.conversation_messages[i].role == "user":
                                user_message = st.session_state.conversation_messages[i].content
                                break

                        if user_message:
                            # Get conversation history up to the user message
                            history_up_to_user = st.session_state.conversation_messages[:regen_index]

                            # Remove the assistant message being regenerated
                            st.session_state.conversation_messages = st.session_state.conversation_messages[:regen_index]

                            # Clear regeneration flag
                            st.session_state.regenerating_message_id = None

                            # Process regeneration
                            try:
                                # Add user message to display
                                with st.chat_message("user"):
                                    st.write(user_message)

                                # Generate new response
                                with st.spinner("Regenerating response..."):
                                    response = asyncio.run(
                                        generate_llm_response(
                                            user_message,
                                            history_up_to_user,
                                            current_llm_info
                                        )
                                    )

                                # Create and add new assistant message
                                assistant_msg = Message(
                                    role="assistant",
                                    content=response
                                )

                                # Add to database and session state
                                conversation_manager.add_message(
                                    st.session_state.current_conversation_id,
                                    assistant_msg
                                )
                                st.session_state.conversation_messages.append(assistant_msg)

                                # Display the new response
                                with st.chat_message("assistant"):
                                    st.write(response)

                                log("info", "LLM response regenerated and saved")
                                st.rerun()

                            except Exception as e:
                                error_msg = f"Error regenerating response: {str(e)}"
                                log("error", error_msg, exc_info=True)
                                st.error(error_msg)
                                # Restore original messages if regeneration failed
                                conversation = conversation_manager.get_conversation(
                                    st.session_state.current_conversation_id,
                                    include_messages=True
                                )
                                if conversation:
                                    st.session_state.conversation_messages = conversation.messages
                                st.rerun()
                        else:
                            st.error("Could not find user message to regenerate from")
                            st.session_state.regenerating_message_id = None
                            st.rerun()

                    # Display streaming buffer if active
                    if st.session_state.streaming_active and st.session_state.stream_buffer:
                        with st.chat_message("assistant"):
                            st.markdown(st.session_state.stream_buffer)
                            st.caption("⏳ " + _("streaming_in_progress"))

                    # Chat input at the bottom
                    st.divider()

                    # Text area for user input
                    user_message = st.chat_input(
                        _("enter_message"),
                        key="chat_input"
                    )

                    if user_message:
                        # Add user message to conversation
                        user_msg = Message(
                            role="user",
                            content=user_message.strip()
                        )

                        # Add to database and session state
                        try:
                            message_id = conversation_manager.add_message(
                                st.session_state.current_conversation_id,
                                user_msg
                            )
                            st.session_state.conversation_messages.append(user_msg)

                            log("info", f"Sending message to LLM: {user_message[:50]}...")

                            # Generate LLM response with conversation history
                            with st.spinner("Thinking..."):
                                response = asyncio.run(
                                    generate_llm_response(
                                        user_message.strip(),
                                        st.session_state.conversation_messages,
                                        current_llm_info
                                    )
                                )

                            # Create assistant message
                            assistant_msg = Message(
                                role="assistant",
                                content=response
                            )

                            # Add to database and session state
                            conversation_manager.add_message(
                                st.session_state.current_conversation_id,
                                assistant_msg
                            )
                            st.session_state.conversation_messages.append(assistant_msg)

                            # If streaming didn't work, show the full response
                            if not st.session_state.stream_buffer and response:
                                with st.chat_message("assistant"):
                                    st.markdown(response)

                            log("info", "LLM response received and saved")

                            # Rerun to update the display
                            st.rerun()

                        except Exception as e:
                            error_msg = f"Error processing message: {str(e)}"
                            log("error", error_msg, exc_info=True)
                            st.error(error_msg)
                else:
                    st.warning("Conversation not found. Please select another conversation.")
                    st.session_state.current_conversation_id = None
                    st.session_state.conversation_messages = []
        else:
            # INJECTION POINT 4: Main Content when no user is logged in
            no_user_contents = ui_registry.render_all("main_no_user")
            for content in no_user_contents:
                if content:
                    st.divider()

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
