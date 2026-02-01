"""
Conversation Management and Chat UI Module
==========================================

This module provides comprehensive conversation management and chat interface
components that can be injected into the main application through the UI registry system.

Combines functionality from:
- conservation_ui.py (typo for conversation management sidebar)
- conversation_ui.py (main chat interface)
"""

import streamlit as st
import asyncio
from shared.conversation import conversation_manager, Message
from shared.logging import log
from shared.llm import llm_generate, get_current_llm_info
from shared.translate import _
from modules.rag_manager import rag_manager
from shared.llm import register_llm_callback
from typing import List, Dict, Optional, Tuple, Any, Callable


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
        # Get current user ID for RAG context
        user_id = None
        if st.session_state.current_user:
            user_id = st.session_state.current_user['id']

        # Use llm_generate with conversation history and RAG context
        response = await llm_generate(
            user_message.strip(),
            stream_callback,
            conversation_history=llm_history,
            user_id=user_id if st.session_state.rag_enabled else None
        )

        st.session_state.streaming_active = False
        return response
    except Exception as e:
        error_msg = f"Error calling LLM: {str(e)}"
        log("error", error_msg, exc_info=True)
        st.session_state.streaming_active = False
        raise Exception(error_msg)


def inject_ui_initialize():
    """Initialize conversation-related session state variables."""
    log("debug", "Initializing conversation UI session state")

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

    # Initialize session state for RAG
    if "rag_enabled" not in st.session_state:
        st.session_state.rag_enabled = True

    # Register RAG callback if not already registered
    if not hasattr(st.session_state, '_rag_callback'):
        rag_callback = create_rag_context_callback()
        register_llm_callback(rag_callback)
        st.session_state._rag_callback = rag_callback
        log("debug", "Registered RAG context callback")

    return True


def inject_ui_sidebar():
    """Render conversation management section in the sidebar."""
    # Only show if user is logged in
    if not st.session_state.current_user:
        log("debug", "No current user, skipping conversation sidebar")
        st.warning("Please log in to access your conversations.")
        return False

    log("debug", f"Current user: {st.session_state.current_user.get('name')} (ID: {st.session_state.current_user.get('id')})")

    st.title("💬 Conversations")

    # Button to create new conversation
    if st.button("➕ New Conversation", type="primary", use_container_width=True):
        st.session_state.show_new_conversation_form = True
        st.session_state.editing_conversation_id = None
        st.rerun()

    try:
        # Get user's conversations
        from shared.conversation import conversation_manager
        user_conversations = conversation_manager.get_user_conversations(
            st.session_state.current_user['id'],
            include_inactive=False
        )

        # DEBUG: Log the conversations found
        log("debug", f"Found {len(user_conversations)} conversations for user {st.session_state.current_user['id']}")

    except Exception as e:
        log("error", f"Error getting user conversations: {e}", exc_info=True)
        user_conversations = []
        st.error(f"Error loading conversations: {str(e)}")

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
                button_label = f"{'▶️' if not is_current else '📝'} {conv['title']}"
                if st.button(
                    button_label,
                    key=f"select_{conv_key}",
                    help=f"Select this conversation ({conv['message_count']} messages)",
                    use_container_width=True,
                    type="primary" if is_current else "secondary"
                ):
                    # Load this conversation
                    st.session_state.current_conversation_id = conv['id']
                    try:
                        conversation = conversation_manager.get_conversation(conv['id'], include_messages=True)
                        if conversation:
                            st.session_state.conversation_messages = conversation.messages
                        log("info", f"Loaded conversation: {conv['title']} ({conv['id']})")
                    except Exception as e:
                        log("error", f"Error loading conversation {conv['id']}: {e}")
                        st.error(f"Error loading conversation: {str(e)}")
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

    return True


def render_conversation_form():
    """Render the conversation creation/editing form."""
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
                    current_llm_info = get_current_llm_info()

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


def inject_ui_main_before_conversation():
    """
    Render conversation interface when appropriate.
    This uses a namespaced function name to avoid conflicts with main_before_conversation().
    """
    # First check if we need to show the conversation form
    if st.session_state.current_user and st.session_state.show_new_conversation_form:
        render_conversation_form()
        return True

    # Only render if we're on chat page and user is logged in
    if (st.session_state.get('current_page') == 'chat' and
        st.session_state.get('current_user') and
        st.session_state.get('current_conversation_id')):
        return show_conversation_interface()
    return None


def inject_ui_main_content():
    """Render content when no user is logged in or no conversation is selected."""
    # Check if we're on the chat page
    if st.session_state.get('current_page') != 'chat':
        return None

    # If no user is logged in
    if not st.session_state.get('current_user'):
        st.info("👤 Please log in to start chatting.")
        return True

    # If user is logged in but no conversation is selected
    if (st.session_state.get('current_user') and
        not st.session_state.get('current_conversation_id')):
        st.divider()
        st.info("💬 Select a conversation from the sidebar or create a new one to start chatting.")
        return True

    return None

def show_conversation_interface():
    """Display the conversation chat interface."""
    # Get current conversation info
    current_conv = conversation_manager.get_conversation(
        st.session_state.current_conversation_id,
        include_messages=False
    )

    if current_conv:
        # Conversation header
        col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])  # Added col5
        with col1:
            st.subheader(f"💬 {current_conv.title}")
        with col2:
            # RAG toggle
            rag_enabled = st.toggle("🔍 RAG",
                                  value=st.session_state.rag_enabled,
                                  help="Enable/disable RAG context retrieval")
            if rag_enabled != st.session_state.rag_enabled:
                st.session_state.rag_enabled = rag_enabled
                st.rerun()
        with col3:
            # Refresh button
            if st.button("🔄 Refresh", help="Reload conversation from database"):
                conversation = conversation_manager.get_conversation(
                    st.session_state.current_conversation_id,
                    include_messages=True
                )
                if conversation:
                    st.session_state.conversation_messages = conversation.messages
                st.rerun()
        with col4:
            # Clear button
            if st.button("🗑️ Clear", help="Clear all messages in this conversation"):
                if conversation_manager.clear_conversation_messages(st.session_state.current_conversation_id):
                    st.session_state.conversation_messages = []
                    st.success("Conversation cleared")
                    st.rerun()
        with col5:
            # Regenerate button
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

                # Get current LLM info
                current_llm_info = get_current_llm_info()

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

                # Get current LLM info
                current_llm_info = get_current_llm_info()

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
        st.rerun()

    return True

def create_rag_context_callback():
    """Create a callback function that adds RAG context to LLM queries."""
    def rag_context_callback(user_id: str, messages: List[Dict]) -> str:
        """Callback to add RAG context from user's documents."""
        try:
            # Get the last user message
            last_user_message = None
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    last_user_message = msg.get("content", "")
                    break

            if not last_user_message:
                return ""

            # Get RAG context from default engine
            context = rag_manager.get_rag_context(user_id, last_user_message)
            return context

        except Exception as e:
            log("error", f"RAG context callback failed: {e}")
            return ""

    return rag_context_callback
