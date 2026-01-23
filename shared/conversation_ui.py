# file name: shared/conversation_ui.py
"""
Conversation UI Module

Provides the conversation interface for chatting with LLMs,
including message display, input handling, and regeneration features.
"""

import streamlit as st
import asyncio
from shared.logging import log
from shared.conversation import conversation_manager, Message
from shared.llm import get_current_llm_info
from shared.translate import _streamlit as _

# Import helper functions from main app
from app import generate_llm_response, get_conversation_history_for_llm

def show_conversation_interface():
    """Display the conversation interface."""
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

def conversation_render_main_before_conversation():
    """Render conversation interface when appropriate."""
    # Only render if we're on chat page and user is logged in
    if (st.session_state.get('current_page') == 'chat' and
        st.session_state.get('current_user') and
        st.session_state.get('current_conversation_id')):
        return show_conversation_interface()
    return None

def conversation_render_main_no_user():
    """Render content when no user is logged in."""
    if st.session_state.get('current_page') == 'chat' and not st.session_state.get('current_user'):
        st.info("👤 Please log in to start chatting.")
        return True
    return None

# Export functions for UI registry
sidebar = None
main_header = None
main_before_conversation = conversation_render_main_before_conversation
main_no_user = conversation_render_main_no_user
main_after_conversation = None
main_footer = None
