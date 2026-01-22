"""
Conversation Management UI Module
=================================

This module provides UI components for conversation management that can be
injected into the main application through the UI registry system.
"""

import streamlit as st
from shared.conversation import conversation_manager
from shared.logging import log
from shared.llm import get_current_llm_info

def sidebar():
    """Render conversation management section in the sidebar."""
    # Only show if user is logged in
    if not st.session_state.current_user:
        return False

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

    return True

def main_before_conversation():
    """Render conversation form if triggered."""
    if st.session_state.current_user and st.session_state.show_new_conversation_form:
        render_conversation_form()
        return True
    return False

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
