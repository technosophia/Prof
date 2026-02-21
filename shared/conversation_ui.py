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
from datetime import datetime
from shared.common import _, log, Message
from shared.cached import get_config, get_conversation_manager
from shared.common import llm_conversation_generate, get_current_llm_info
from typing import List, Dict, Optional, Tuple, Any, Callable
from shared.ui_registry import UIRegistry
from shared.cached import get_conversation_manager


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

        # Use llm_conversation_generate with conversation history and RAG context
        response = await llm_conversation_generate(
            user_message.strip(),
            stream_callback,
            conversation_history=llm_history,
            user_id=user_id
        )

        st.session_state.streaming_active = False
        # Return both response and llm_id
        return response, current_llm_info.get("id") if current_llm_info else None
    except Exception as e:
        error_msg = f"Error calling LLM: {str(e)}"
        log("error", error_msg, exc_info=True)
        st.session_state.streaming_active = False
        # Use translated error message for user-facing error
        st.error(_("error_llm_call").format(error=str(e)))
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

    if "show_delete_conversation_dialog" not in st.session_state:
        st.session_state.show_delete_conversation_dialog = False

    return True


def inject_ui_sidebar():
    """Render conversation management section in the sidebar."""
    # Only show if user is logged in
    if not st.session_state.current_user:
        log("debug", "No current user, skipping conversation sidebar")
        st.warning(_("login_required_warning"))
        return False

    log("debug", f"Current user: {st.session_state.current_user.get('name')} (ID: {st.session_state.current_user.get('id')})")

    st.title(_("conversations_title"))

    # Button to create new conversation
    if st.button(_("new_conversation_button"), type="primary", use_container_width=True):
        log("info", "Creating new conversation")
        st.session_state.show_new_conversation_form = True
        st.session_state.editing_conversation_id = None
        # Switch to chat page when starting new conversation
        st.session_state.current_page = "chat"
        st.rerun()

    try:
        # Get user's conversations
        user_conversations = get_conversation_manager().get_user_conversations(
            st.session_state.current_user['id'],
            include_inactive=False
        )

        # DEBUG: Log the conversations found
        log("debug", f"Found {len(user_conversations)} conversations for user {st.session_state.current_user['id']}")

    except Exception as e:
        log("error", f"Error getting user conversations: {e}", exc_info=True)
        user_conversations = []
        st.error(_("error_loading_conversations").format(error=str(e)))

    if user_conversations:
        st.subheader(_("your_conversations"))

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
                    help=_("select_conversation").format(count=conv['message_count']),
                    use_container_width=True,
                    type="primary" if is_current else "secondary"
                ):
                    # Load this conversation
                    st.session_state.current_conversation_id = conv['id']
                    # Switch to chat page when selecting a conversation
                    st.session_state.current_page = "chat"
                    try:
                        conversation = get_conversation_manager().get_conversation(conv['id'], include_messages=True)
                        if conversation:
                            st.session_state.conversation_messages = conversation.messages
                        log("info", f"Loaded conversation: {conv['title']} ({conv['id']})")
                    except Exception as e:
                        log("error", f"Error loading conversation {conv['id']}: {e}")
                        st.error(_("error_loading_conversation").format(error=str(e)))
                    st.rerun()

            with col2:
                # Button to edit conversation title
                if st.button("✏️", key=f"edit_{conv_key}", help=_("edit_conversation_title")):
                    st.session_state.editing_conversation_id = conv['id']
                    st.session_state.show_new_conversation_form = True
                    # Switch to chat page when editing conversation
                    st.session_state.current_page = "chat"
                    st.rerun()

        # Show current conversation info
        if st.session_state.current_conversation_id:
            current_conv = next(
                (c for c in user_conversations if c['id'] == st.session_state.current_conversation_id),
                None
            )
            if current_conv:
                st.info(_("current_conversation_info").format(title=current_conv['title']))
                st.caption(_("messages_count").format(count=current_conv['message_count']))
    else:
        st.info(_("no_conversations_yet"))

    return True


def render_conversation_form():
    """Render the conversation creation/editing form."""
    st.divider()

    if st.session_state.editing_conversation_id:
        st.subheader(_("edit_conversation"))
        # Get current title for editing
        current_conv = get_conversation_manager().get_conversation(
            st.session_state.editing_conversation_id,
            include_messages=False
        )
        default_title = current_conv.title if current_conv else "My Conversation"
    else:
        st.subheader(_("create_conversation"))
        default_title = st.session_state.new_conversation_title

    with st.form("conversation_form"):
        title = st.text_input(_("conversation_title_label"), value=default_title)

        col1, col2 = st.columns(2)
        with col1:
            submit = st.form_submit_button(_("save_button"), type="primary")
        with col2:
            cancel = st.form_submit_button(_("cancel_button"))

        if submit:
            if not title.strip():
                st.error(_("conversation_title_required"))
            else:
                try:
                    current_llm_info = get_current_llm_info()

                    if st.session_state.editing_conversation_id:
                        # Update existing conversation title
                        success = get_conversation_manager().update_conversation_title(
                            st.session_state.editing_conversation_id,
                            title.strip()
                        )
                        if success:
                            st.success(_("conversation_updated_success"))
                            log("info", f"Conversation title updated: {title.strip()}")

                            # If we're editing the current conversation, update session state
                            if st.session_state.current_conversation_id == st.session_state.editing_conversation_id:
                                # Reload the conversation to get updated title
                                conversation = get_conversation_manager().get_conversation(
                                    st.session_state.current_conversation_id,
                                    include_messages=True
                                )
                                if conversation:
                                    st.session_state.conversation_messages = conversation.messages
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

                        conversation_id = get_conversation_manager().create_conversation(
                            user_id=st.session_state.current_user['id'],
                            title=title.strip(),
                            system_prompt=None,
                            llm_config=llm_config
                        )
                        st.success(_("conversation_created_success"))
                        log("info", f"Conversation created: {title.strip()} (ID: {conversation_id})")

                        # Set as current conversation
                        st.session_state.current_conversation_id = conversation_id
                        st.session_state.conversation_messages = []

                    # Reset form state
                    st.session_state.show_new_conversation_form = False
                    st.session_state.editing_conversation_id = None
                    # Ensure we're on the chat page after creating/editing
                    st.session_state.current_page = "chat"
                    st.rerun()
                except Exception as e:
                    st.error(_("error_processing_message").format(error=str(e)))
                    log("error", f"Conversation form error: {str(e)}")

        if cancel:
            st.session_state.show_new_conversation_form = False
            st.session_state.editing_conversation_id = None
            # Switch back to chat page when canceling
            st.session_state.current_page = "chat"
            st.rerun()


def inject_ui_main_content():
    """Render content when no user is logged in or no conversation is selected."""
    # Check if we're on the chat page
    if st.session_state.get('current_page') != 'chat':
        return None

    # If no user is logged in
    if not st.session_state.get('current_user'):
        st.info(_("no_conversation_selected"))
        return True

    # Check if we need to show the new conversation form
    if st.session_state.current_user and st.session_state.show_new_conversation_form:
        render_conversation_form()
        return True

    # If user is logged in but no conversation is selected
    if (st.session_state.get('current_user') and
        not st.session_state.get('current_conversation_id')):
        st.divider()
        st.info(_("select_conversation_from_sidebar"))
        return True

    # Only render if we're on chat page and user is logged in with a conversation
    if (st.session_state.get('current_page') == 'chat' and
        st.session_state.get('current_user') and
        st.session_state.get('current_conversation_id')):
        return show_conversation_interface()

    return None

def show_conversation_interface():
    """Display the conversation chat interface."""
    # Get current conversation info
    current_conv = get_conversation_manager().get_conversation(
        st.session_state.current_conversation_id,
        include_messages=False
    )

    if current_conv:
        # Conversation header
        col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])
        with col1:
            st.subheader(f"💬 {current_conv.title}")
        with col2:
            # Refresh button
            if st.button(_("refresh_button"), help=_("refresh_help")):
                conversation = get_conversation_manager().get_conversation(
                    st.session_state.current_conversation_id,
                    include_messages=True
                )
                if conversation:
                    st.session_state.conversation_messages = conversation.messages
                st.rerun()
        with col3:
            # Clear button
            if st.button(_("clear_button"), help=_("clear_help")):
                if get_conversation_manager().clear_conversation_messages(st.session_state.current_conversation_id):
                    st.session_state.conversation_messages = []
                    st.success(_("clear_success"))
                    st.rerun()
        with col4:
            # Regenerate button
            has_messages = len(st.session_state.conversation_messages) > 0
            last_is_assistant = has_messages and st.session_state.conversation_messages[-1].role == "assistant"

            if st.button(_("regenerate_button"),
                       help=_("regenerate_help"),
                       disabled=not (has_messages and last_is_assistant),
                       type="secondary"):
                # Set regeneration flag and trigger regeneration
                st.session_state.regenerating_message_id = len(st.session_state.conversation_messages) - 1
                st.rerun()
        with col5:
            # Delete conversation button
            if st.button(_("delete_button"),
                        help=_("delete_help"),
                        type="secondary"):
                st.session_state.show_delete_conversation_dialog = True
                st.rerun()

        # Display conversation messages
        st.session_state.ui_registry.render_all("inside_conversation")
        st.divider()

        if st.session_state.conversation_messages:
            for i, message in enumerate(st.session_state.conversation_messages):
                if message.role == "user":
                    with st.chat_message("user"):
                        st.write(message.content)
                elif message.role == "assistant":
                    with st.chat_message("assistant"):
                        st.write(message.content)

                        # Show which LLM generated this response
                        if message.llm_id:
                            # You might want to get the LLM name from the manager
                            st.caption(_("generated_by").format(llm_name=message.llm_id))

                        # Add regenerate button for each assistant message
                        if i == len(st.session_state.conversation_messages) - 1:
                            col_a, col_b = st.columns([1, 6])
                            with col_a:
                                if st.button("🔄",
                                           key=f"regenerate_{i}",
                                           help=_("regenerate_this_response")):
                                    st.session_state.regenerating_message_id = i
                                    st.rerun()

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
                    with st.spinner(_("thinking")):
                        response, llm_id = asyncio.run(
                            generate_llm_response(
                                user_message,
                                history_up_to_user,
                                current_llm_info
                            )
                        )

                    # Create and add new assistant message
                    assistant_msg = Message(
                        role="assistant",
                        content=response,
                        llm_id=llm_id
                    )

                    # Add to database and session state
                    get_conversation_manager().add_message(
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
                    error_msg = _("error_regenerating").format(error=str(e))
                    log("error", f"Error regenerating response: {str(e)}", exc_info=True)
                    st.error(error_msg)
                    # Restore original messages if regeneration failed
                    conversation = get_conversation_manager().get_conversation(
                        st.session_state.current_conversation_id,
                        include_messages=True
                    )
                    if conversation:
                        st.session_state.conversation_messages = conversation.messages
                    st.rerun()
            else:
                st.error(_("user_message_not_found"))
                st.session_state.regenerating_message_id = None
                st.rerun()

        # Delete conversation dialog
        if st.session_state.get('show_delete_conversation_dialog'):
            st.divider()
            st.error(_("delete_conversation_title"))
            st.warning(_("delete_conversation_confirmation").format(title=current_conv.title))
            st.warning(_("delete_conversation_warning"))

            col_del1, col_del2 = st.columns(2)
            with col_del1:
                if st.button(_("yes_delete"), type="primary"):
                    if get_conversation_manager().delete_conversation(st.session_state.current_conversation_id):
                        st.success(_("conversation_deleted").format(title=current_conv.title))
                        st.session_state.current_conversation_id = None
                        st.session_state.conversation_messages = []
                        st.session_state.show_delete_conversation_dialog = False
                        st.rerun()
                    else:
                        st.error(_("delete_failed"))
            with col_del2:
                if st.button(_("no_cancel")):
                    st.session_state.show_delete_conversation_dialog = False
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
                message_id = get_conversation_manager().add_message(
                    st.session_state.current_conversation_id,
                    user_msg
                )
                st.session_state.conversation_messages.append(user_msg)

                log("info", f"Sending message to LLM: {user_message[:50]}...")

                # Get current LLM info
                current_llm_info = get_current_llm_info()

                # Generate LLM response with conversation history
                with st.spinner(_("thinking")):
                    response, llm_id = asyncio.run(
                        generate_llm_response(
                            user_message.strip(),
                            st.session_state.conversation_messages,
                            current_llm_info
                        )
                    )
                # Create assistant message with llm_id
                assistant_msg = Message(
                    role="assistant",
                    content=response,
                    llm_id=llm_id  # NEW: Store which LLM generated this
                )

                # Add to database and session state
                get_conversation_manager().add_message(
                    st.session_state.current_conversation_id,
                    assistant_msg
                )
                st.session_state.conversation_messages.append(assistant_msg)

                # If streaming didn't work, show the full response
                if not st.session_state.stream_buffer and response:
                    with st.chat_message("assistant"):
                        st.markdown(response)
                        if current_llm_info:
                            st.caption(_("generated_by").format(llm_name=current_llm_info.get('name', 'Unknown LLM')))

                log("info", f"LLM response received and saved (LLM: {llm_id})")

                # Rerun to update the display
                st.rerun()

            except Exception as e:
                error_msg = _("error_processing_message").format(error=str(e))
                log("error", f"Error processing message: {str(e)}", exc_info=True)
                st.error(error_msg)
    else:
        st.warning(_("conversation_not_found"))
        st.session_state.current_conversation_id = None
        st.session_state.conversation_messages = []
        st.rerun()

    return True
