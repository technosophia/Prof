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

# Page configuration
st.set_page_config(
    page_title="Multilingual App",
    page_icon="🌍",
    layout="centered"
)

def main():
    # Log main function entry
    log("debug", "Entering main function")

    # Get config inside main function
    current_config = get_config()

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

    # Initialize session state for user management
    if "current_user" not in st.session_state:
        st.session_state.current_user = None
    if "show_user_form" not in st.session_state:
        st.session_state.show_user_form = False
    if "edit_user_id" not in st.session_state:
        st.session_state.edit_user_id = None

    # Sidebar for language, LLM, User management, and Conversations
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

        st.divider()

        # User Management Section
        st.title("👤 User Management")

        # Current user info
        if st.session_state.current_user:
            st.info(f"**Current User:** {st.session_state.current_user['name']}")

            # Switch user button
            if st.button("Switch User"):
                st.session_state.current_user = None
                st.session_state.current_conversation_id = None
                st.session_state.conversation_messages = []
                st.rerun()
        else:
            st.warning("No user selected")

            # User selector - USING get_all_users_dict() instead of get_all_users()
            all_users = user_manager.get_all_users_dict()
            if all_users:
                user_options = ["Select a user..."] + list(all_users.keys())
                user_display = ["Select a user..."] + [f"{user['name']} ({user_id})" for user_id, user in all_users.items()]

                selected_user = st.selectbox(
                    "Choose user",
                    options=user_options,
                    format_func=lambda x: user_display[user_options.index(x)] if x in user_options else x,
                    key="user_selector"
                )

                if selected_user != "Select a user..." and selected_user:
                    if st.button("Login as User"):
                        st.session_state.current_user = all_users[selected_user]
                        log("info", f"User logged in: {st.session_state.current_user['name']}")
                        st.rerun()

        # Create new user button
        if st.button("➕ Create New User", type="primary"):
            st.session_state.show_user_form = True
            st.session_state.edit_user_id = None

        st.divider()

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

        st.divider()

        # Conversation Management Section (only show if user is logged in)
        if st.session_state.current_user:
            st.title("💬 Conversations")

            # Button to create new conversation
            if st.button("➕ New Conversation", type="primary", use_container_width=True):
                st.session_state.show_new_conversation_form = True
                st.session_state.editing_conversation_id = None

            # Get user's conversations
            user_conversations = conversation_manager.get_user_conversations(
                st.session_state.current_user['id'],
                include_inactive=False
            )

            if user_conversations:
                st.subheader("Your Conversations")

                # Display conversations as selectable items
                for conv in user_conversations:
                    # Create a unique key for each conversation button
                    conv_key = f"conv_{conv['id']}"

                    # Determine if this is the current conversation
                    is_current = st.session_state.current_conversation_id == conv['id']

                    # Create columns for the conversation item
                    col1, col2 = st.columns([4, 1])

                    with col1:
                        # Button to select conversation
                        if st.button(
                            f"{'▶️' if not is_current else '📝'} {conv['title']}",
                            key=f"select_{conv_key}",
                            help=f"Select this conversation ({conv['message_count']} messages)",
                            use_container_width=True,
                            type="primary" if is_current else "secondary"
                        ):
                            # Load this conversation
                            st.session_state.current_conversation_id = conv['id']
                            conversation = conversation_manager.get_conversation(conv['id'], include_messages=True)
                            if conversation:
                                st.session_state.conversation_messages = conversation.messages
                            log("info", f"Loaded conversation: {conv['title']} ({conv['id']})")
                            st.rerun()

                    with col2:
                        # Button to edit conversation title
                        if st.button("✏️", key=f"edit_{conv_key}", help="Edit conversation title"):
                            st.session_state.editing_conversation_id = conv['id']
                            st.session_state.show_new_conversation_form = True
                            st.rerun()

                # Show current conversation info
                if st.session_state.current_conversation_id:
                    current_conv = next(
                        (c for c in user_conversations if c['id'] == st.session_state.current_conversation_id),
                        None
                    )
                    if current_conv:
                        st.info(f"**Current:** {current_conv['title']}")
                        st.caption(f"Messages: {current_conv['message_count']}")
            else:
                st.info("No conversations yet. Create your first one!")

        st.divider()
        st.caption(_("current_language"))

        # Show current LLM info in sidebar
        if current_llm_info:
            st.info(f"**Current LLM:** {current_llm_info['name']}")
            st.caption(f"Type: {current_llm_info['type']}")
            st.caption(f"Model: {current_llm_info['model']}")
            st.caption(f"Status: {'✅ Available' if current_llm_info['available'] else '❌ Unavailable'}")

    # Main content
    st.title(_("hello_world"))

    # Show current user info if logged in
    if st.session_state.current_user:
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.success(f"✅ Logged in as: **{st.session_state.current_user['name']}**")
        with col2:
            if st.button("👤 Profile"):
                st.session_state.edit_user_id = st.session_state.current_user['id']
                st.session_state.show_user_form = True
        with col3:
            if st.button("🚪 Logout"):
                st.session_state.current_user = None
                st.session_state.current_conversation_id = None
                st.session_state.conversation_messages = []
                st.rerun()
    else:
        st.warning("👤 Please select or create a user from the sidebar to start conversations.")

    # Log that we're displaying main content
    log("debug", "Displaying main content")

    # New Conversation Form (shown when creating/editing conversations)
    if st.session_state.show_new_conversation_form and st.session_state.current_user:
        st.divider()

        if st.session_state.editing_conversation_id:
            st.subheader("✏️ Edit Conversation Title")
            # Get current title for editing
            current_conv = conversation_manager.get_conversation(
                st.session_state.editing_conversation_id,
                include_messages=False
            )
            default_title = current_conv.title if current_conv else "My Conversation"
        else:
            st.subheader("➕ Create New Conversation")
            default_title = st.session_state.new_conversation_title

        with st.form("conversation_form"):
            title = st.text_input("Conversation Title *", value=default_title)

            col1, col2 = st.columns(2)
            with col1:
                submit = st.form_submit_button("💾 Save", type="primary")
            with col2:
                cancel = st.form_submit_button("❌ Cancel")

            if submit:
                if not title.strip():
                    st.error("Conversation title is required")
                else:
                    try:
                        if st.session_state.editing_conversation_id:
                            # Update existing conversation title
                            success = conversation_manager.update_conversation_title(
                                st.session_state.editing_conversation_id,
                                title.strip()
                            )
                            if success:
                                st.success("Conversation updated successfully!")
                                log("info", f"Conversation title updated: {title.strip()}")

                                # If we're editing the current conversation, update session state
                                if st.session_state.current_conversation_id == st.session_state.editing_conversation_id:
                                    # Reload the conversation to get updated title
                                    conversation = conversation_manager.get_conversation(
                                        st.session_state.current_conversation_id,
                                        include_messages=True
                                    )
                                    if conversation:
                                        st.session_state.conversation_messages = conversation.messages
                            else:
                                st.error("Failed to update conversation")
                        else:
                            # Create new conversation
                            # Create new conversation
                            # Extract only serializable parts from llm_info
                            llm_config = {}
                            if current_llm_info:
                                # Create a clean dictionary with only serializable data
                                llm_config = {
                                    "id": current_llm_info.get("id", ""),
                                    "name": current_llm_info.get("name", ""),
                                    "type": current_llm_info.get("type", ""),
                                    "model": current_llm_info.get("model", ""),
                                    "available": current_llm_info.get("available", False),
                                    "description": current_llm_info.get("description", ""),
                                    "enabled": current_llm_info.get("enabled", True)
                                    # Don't include the 'engine' object or any non-serializable data
                                }
                                # Remove any None values
                                llm_config = {k: v for k, v in llm_config.items() if v is not None}

                            conversation_id = conversation_manager.create_conversation(
                                user_id=st.session_state.current_user['id'],
                                title=title.strip(),
                                system_prompt=None,
                                llm_config=llm_config
                            )
                            st.success(f"Conversation created successfully!")
                            log("info", f"Conversation created: {title.strip()} (ID: {conversation_id})")

                            # Set as current conversation
                            st.session_state.current_conversation_id = conversation_id
                            st.session_state.conversation_messages = []

                        # Reset form state
                        st.session_state.show_new_conversation_form = False
                        st.session_state.editing_conversation_id = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
                        log("error", f"Conversation form error: {str(e)}")

            if cancel:
                st.session_state.show_new_conversation_form = False
                st.session_state.editing_conversation_id = None
                st.rerun()

    # User Management Form (shown when creating/editing users)
    if st.session_state.show_user_form:
        st.divider()
        st.subheader("👤 " + ("Edit User" if st.session_state.edit_user_id else "Create New User"))

        with st.form("user_form"):
            if st.session_state.edit_user_id:
                # Editing existing user
                user = user_manager.get_user(st.session_state.edit_user_id)
                default_name = user["name"] if user else ""
                default_email = user["email"] if user else ""
            else:
                # Creating new user
                default_name = ""
                default_email = ""

            name = st.text_input("Name *", value=default_name)
            email = st.text_input("Email", value=default_email)

            col1, col2 = st.columns(2)
            with col1:
                submit = st.form_submit_button("💾 Save User", type="primary")
            with col2:
                cancel = st.form_submit_button("❌ Cancel")

            if submit:
                if not name.strip():
                    st.error("Name is required")
                else:
                    try:
                        if st.session_state.edit_user_id:
                            # Update existing user
                            success = user_manager.update_user(
                                st.session_state.edit_user_id,
                                name=name.strip(),
                                email=email.strip() if email else None
                            )
                            if success:
                                st.success("User updated successfully!")
                                # Update current user if editing self
                                if (st.session_state.current_user and
                                    st.session_state.current_user['id'] == st.session_state.edit_user_id):
                                    st.session_state.current_user = user_manager.get_user(st.session_state.edit_user_id)
                                log("info", f"User updated: {name}")
                            else:
                                st.error("Failed to update user")
                        else:
                            # Create new user
                            user_id = user_manager.create_user(
                                name=name.strip(),
                                email=email.strip() if email else None
                            )
                            st.success(f"User created successfully! ID: {user_id}")
                            log("info", f"User created: {name} (ID: {user_id})")

                        # Reset form state
                        st.session_state.show_user_form = False
                        st.session_state.edit_user_id = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
                        log("error", f"User form error: {str(e)}")

            if cancel:
                st.session_state.show_user_form = False
                st.session_state.edit_user_id = None
                st.rerun()

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
                col1, col2, col3 = st.columns([4, 1, 1])
                with col1:
                    st.subheader(f"💬 {current_conv.title}")
                with col2:
                    if st.button("🔄 Refresh", help="Reload conversation from database"):
                        conversation = conversation_manager.get_conversation(
                            st.session_state.current_conversation_id,
                            include_messages=True
                        )
                        if conversation:
                            st.session_state.conversation_messages = conversation.messages
                        st.rerun()
                with col3:
                    if st.button("🗑️ Clear", help="Clear all messages in this conversation"):
                        if conversation_manager.clear_conversation_messages(st.session_state.current_conversation_id):
                            st.session_state.conversation_messages = []
                            st.success("Conversation cleared")
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
                        elif message.role == "system":
                            with st.container():
                                st.markdown(f"*System: {message.content}*")

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

                        # Clear previous streaming buffer
                        st.session_state.stream_buffer = ""
                        st.session_state.streaming_active = True

                        # Create a placeholder for the streaming response
                        response_placeholder = st.empty()

                        # Define streaming callback
                        def stream_callback(chunk):
                            st.session_state.stream_buffer += chunk
                            response_placeholder.markdown(st.session_state.stream_buffer)

                        # Run async LLM call
                        try:
                            # Prepare conversation history for LLM
                            conversation_history = []
                            for msg in st.session_state.conversation_messages:
                                if msg.role in ["user", "assistant", "system"]:
                                    conversation_history.append({
                                        "role": msg.role,
                                        "content": msg.content
                                    })

                            # Use llm_generate with conversation history
                            try:
                                # First try the simple version (no conversation history)
                                response = asyncio.run(llm_generate(user_message.strip(), stream_callback))
                            except TypeError as e:
                                # If that fails, the function might have changed
                                # Check if it supports conversation_history
                                if "conversation_history" in str(e):
                                    # Try without conversation_history
                                    response = asyncio.run(llm_generate(user_message.strip(), stream_callback))
                                else:
                                    # Re-raise other errors
                                    raise

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

                            st.session_state.streaming_active = False

                            # If streaming didn't work, show the full response
                            if not st.session_state.stream_buffer and response:
                                with st.chat_message("assistant"):
                                    st.markdown(response)

                            log("info", "LLM response received and saved")

                            # Rerun to update the display
                            st.rerun()

                        except Exception as e:
                            error_msg = f"Error calling LLM: {str(e)}"
                            log("error", error_msg, exc_info=True)
                            st.error(error_msg)
                            st.session_state.streaming_active = False

                    except Exception as e:
                        error_msg = f"Error saving message: {str(e)}"
                        log("error", error_msg, exc_info=True)
                        st.error(error_msg)
            else:
                st.warning("Conversation not found. Please select another conversation.")
                st.session_state.current_conversation_id = None
                st.session_state.conversation_messages = []

    # Debug section in sidebar expander
    with st.expander("🔧 " + _("debug_info")):
        st.write(f"**Current language:** {translator.get_current_language()}")
        st.write(f"**Available languages:** {', '.join(available_langs)}")
        st.write(f"**Log level from config:** {current_config.get('logging.level', 'INFO')}")
        st.write(f"**App name:** {current_config.get('app.name')}")
        st.write(f"**App version:** {current_config.get('app.version')}")

        # User info
        st.write("**User Info:**")
        if st.session_state.current_user:
            st.write(f"- Current User: {st.session_state.current_user['name']} ({st.session_state.current_user['id']})")
            st.write(f"- Email: {st.session_state.current_user['email']}")
            st.write(f"- Created: {st.session_state.current_user['created_at']}")
            st.write(f"- Active: {st.session_state.current_user['is_active']}")

            # Conversation info
            if st.session_state.current_conversation_id:
                st.write("**Current Conversation:**")
                st.write(f"- ID: {st.session_state.current_conversation_id}")
                st.write(f"- Message count: {len(st.session_state.conversation_messages)}")

                # Get conversation from DB for more info
                conv = conversation_manager.get_conversation(
                    st.session_state.current_conversation_id,
                    include_messages=False
                )
                if conv:
                    st.write(f"- Title: {conv.title}")
                    st.write(f"- Created: {conv.created_at}")
                    st.write(f"- Updated: {conv.updated_at}")
        else:
            st.write("- No user logged in")

        st.write(f"**Total Users:** {user_manager.get_user_count()}")

        # Current LLM info
        if current_llm_info:
            st.write("**Current LLM:**")
            st.write(f"- ID: {current_llm_info['id']}")
            st.write(f"- Name: {current_llm_info['name']}")
            st.write(f"- Type: {current_llm_info['type']}")
            st.write(f"- Model: {current_llm_info['model']}")
            st.write(f"- Available: {current_llm_info['available']}")

        # All LLMs info
        st.write("**All LLMs:**")
        for llm_item in available_llms_list:
            status = "🟢" if llm_item["available"] else "🔴"
            st.write(f"- {status} {llm_item['name']} ({llm_item['type']}): {llm_item['description']}")

        # Environment info
        st.write("**Environment Info:**")
        st.write(f"- GEMINI_API_KEY present: {'Yes' if os.getenv('GEMINI_API_KEY') else 'No'}")
        st.write(f"- GROQ_API_KEY present: {'Yes' if os.getenv('GROQ_API_KEY') else 'No'}")
        st.write(f"- OLLAMA_BASE_URL: {os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')}")

        # Database info
        st.write("**Database Info:**")
        st.write(f"- Database path: {db_path}")
        st.write(f"- Data directory exists: {os.path.exists('data')}")

        # Test logging buttons
        st.subheader("Test Logging")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            if st.button("Debug", key="debug_btn"):
                log("debug", "Debug test message from Streamlit")
                st.success("Debug message logged")
        with col2:
            if st.button("Info", key="info_btn"):
                log("info", "Info test message from Streamlit")
                st.success("Info message logged")
        with col3:
            if st.button("Warning", key="warning_btn"):
                log("warning", "Warning test message from Streamlit")
                st.success("Warning message logged")
        with col4:
            if st.button("Error", key="error_btn"):
                log("error", "Error test message from Streamlit", exc_info=False)
                st.success("Error message logged")

        # Test error with traceback
        if st.button("Test Error with Traceback"):
            try:
                # Create a test error
                raise ValueError("This is a test error for traceback")
            except Exception as e:
                log("error", "Test error with traceback", exc_info=True)
                st.success("Error with traceback logged")

if __name__ == "__main__":
    main()
